package io.inhouse.erp.auth;

import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.JWSVerifier;
import com.nimbusds.jose.crypto.ECDSAVerifier;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jose.crypto.MACVerifier;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.org.EmployeeRepository;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.GeneralSecurityException;
import java.security.KeyFactory;
import java.security.PublicKey;
import java.security.SecureRandom;
import java.security.interfaces.ECPublicKey;
import java.security.spec.X509EncodedKeySpec;
import java.text.ParseException;
import java.time.Clock;
import java.time.Instant;
import java.util.Base64;
import java.util.Date;
import java.util.HashSet;
import java.util.HexFormat;
import java.util.List;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * 직원 JWT(HS256, erp가 발급)와 gateway 위임 토큰(ES256, contracts/auth/delegation-token.schema.json)을 확인합니다.
 * 시계 오차는 허용하지 않습니다. 만료 시각이 지나면 바로 401입니다.
 */
@Service
public class TokenService {

    private static final Logger log = LoggerFactory.getLogger(TokenService.class);
    static final String ISSUER = "erp";
    static final String GATEWAY = "gateway";
    static final String AUDIENCE = "erp";

    private final byte[] secret;
    private final long ttlSeconds;
    private final JWSVerifier delegationVerifier;
    private final EmployeeRepository employees;
    private final Clock clock;

    public TokenService(AuthProperties props, EmployeeRepository employees, Clock clock) {
        this.employees = employees;
        this.clock = clock;
        this.ttlSeconds = props.jwtTtlSeconds() > 0 ? props.jwtTtlSeconds() : 3600;
        if (props.jwtSecret() == null || props.jwtSecret().isBlank()) {
            byte[] random = new byte[32];
            new SecureRandom().nextBytes(random);
            this.secret = HexFormat.of().formatHex(random).getBytes(StandardCharsets.UTF_8);
            log.warn("ERP_JWT_SECRET이 없어 임의 키를 만들었습니다. 다시 시작하면 발급한 토큰이 무효가 됩니다");
        } else {
            this.secret = props.jwtSecret().getBytes(StandardCharsets.UTF_8);
            if (secret.length < 32) {
                throw new IllegalStateException("ERP_JWT_SECRET은 32바이트 이상이어야 합니다");
            }
        }
        this.delegationVerifier = loadDelegationVerifier(props.delegationPublicKey());
    }

    public long ttlSeconds() {
        return ttlSeconds;
    }

    public String issue(String employeeId) {
        Instant now = clock.instant();
        JWTClaimsSet claims = new JWTClaimsSet.Builder()
                .issuer(ISSUER).audience(AUDIENCE).subject(employeeId)
                .issueTime(Date.from(now)).expirationTime(Date.from(now.plusSeconds(ttlSeconds)))
                .build();
        try {
            SignedJWT jwt = new SignedJWT(new JWSHeader(JWSAlgorithm.HS256), claims);
            jwt.sign(new MACSigner(secret));
            return jwt.serialize();
        } catch (JOSEException e) {
            throw new IllegalStateException(e);
        }
    }

    /** 토큰을 확인하고 요청한 사람을 돌려줍니다. 어떤 이유로든 확인이 안 되면 401 unauthorized입니다. */
    public ErpPrincipal authenticate(String token) {
        SignedJWT jwt;
        try {
            jwt = SignedJWT.parse(token);
        } catch (ParseException e) {
            throw unauthorized("토큰 형식이 틀렸습니다");
        }
        JWSAlgorithm alg = jwt.getHeader().getAlgorithm();
        try {
            if (JWSAlgorithm.HS256.equals(alg)) {
                JWTClaimsSet c = verified(jwt, new MACVerifier(secret), ISSUER);
                return ErpPrincipal.employee(knownEmployee(c.getSubject()));
            }
            if (JWSAlgorithm.ES256.equals(alg) && delegationVerifier != null) {
                JWTClaimsSet c = verified(jwt, delegationVerifier, GATEWAY);
                String agent = c.getStringClaim("agt");
                String conversation = c.getStringClaim("cid");
                List<String> scopes = c.getStringListClaim("scopes");
                if (agent == null || conversation == null || scopes == null || scopes.contains(null)
                        || c.getIssueTime() == null || c.getJWTID() == null) {
                    throw unauthorized("위임 토큰의 필수 클레임(agt, cid, scopes, iat, jti)이 없습니다");
                }
                return new ErpPrincipal(knownEmployee(c.getSubject()), true, c.getJWTID(), agent, conversation,
                        Set.copyOf(new HashSet<>(scopes)));
            }
        } catch (JOSEException | ParseException e) {
            throw unauthorized("토큰을 확인하지 못했습니다");
        }
        throw unauthorized("지원하지 않는 토큰입니다");
    }

    private JWTClaimsSet verified(SignedJWT jwt, JWSVerifier verifier, String issuer)
            throws JOSEException, ParseException {
        if (!jwt.verify(verifier)) {
            throw unauthorized("서명이 맞지 않습니다");
        }
        JWTClaimsSet c = jwt.getJWTClaimsSet();
        if (!issuer.equals(c.getIssuer())) {
            throw unauthorized("발급자가 맞지 않습니다");
        }
        if (c.getAudience() == null || !c.getAudience().contains(AUDIENCE)) {
            throw unauthorized("대상(aud)에 erp가 없습니다");
        }
        Date exp = c.getExpirationTime();
        if (exp == null || !exp.toInstant().isAfter(clock.instant())) {
            throw unauthorized("만료된 토큰입니다");
        }
        return c;
    }

    private String knownEmployee(String id) {
        if (id == null || !employees.existsById(id)) {
            throw unauthorized("없는 직원입니다");
        }
        return id;
    }

    private static ApiException unauthorized(String detail) {
        return new ApiException(401, "unauthorized", detail);
    }

    private static JWSVerifier loadDelegationVerifier(String path) {
        if (path == null || path.isBlank()) {
            log.warn("DELEGATION_TOKEN_PUBLIC_KEY가 없어 위임 토큰을 받지 않습니다");
            return null;
        }
        try {
            String pem = Files.readString(Path.of(path))
                    .replaceAll("-----(BEGIN|END) PUBLIC KEY-----", "").replaceAll("\\s", "");
            PublicKey key = KeyFactory.getInstance("EC")
                    .generatePublic(new X509EncodedKeySpec(Base64.getDecoder().decode(pem)));
            return new ECDSAVerifier((ECPublicKey) key);
        } catch (IOException | JOSEException | GeneralSecurityException | IllegalArgumentException e) {
            throw new IllegalStateException("위임 토큰 공개 키를 읽지 못했습니다: " + path, e);
        }
    }
}
