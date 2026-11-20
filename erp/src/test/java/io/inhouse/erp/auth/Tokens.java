package io.inhouse.erp.auth;

import com.nimbusds.jose.JOSEException;
import com.nimbusds.jose.JWSAlgorithm;
import com.nimbusds.jose.JWSHeader;
import com.nimbusds.jose.crypto.ECDSASigner;
import com.nimbusds.jose.crypto.MACSigner;
import com.nimbusds.jwt.JWTClaimsSet;
import com.nimbusds.jwt.SignedJWT;
import io.inhouse.erp.PostgresTestBase;
import java.security.PrivateKey;
import java.security.interfaces.ECPrivateKey;
import java.time.Instant;
import java.util.Date;
import java.util.List;
import java.util.UUID;
import java.util.function.Consumer;

/** 시험용 토큰. 위임 토큰은 contracts/auth/delegation-token.schema.json의 클레임을 그대로 씁니다. */
public final class Tokens {

    private Tokens() {}

    public static String delegation(String sub, List<String> scopes) {
        return delegation(sub, scopes, b -> {});
    }

    public static String delegation(String sub, List<String> scopes, Consumer<JWTClaimsSet.Builder> tweak) {
        Instant now = Instant.now();
        JWTClaimsSet.Builder b = new JWTClaimsSet.Builder()
                .issuer("gateway").audience(List.of("erp", "mcp")).subject(sub)
                .claim("agt", "hr").claim("cid", "cnv_test").claim("scopes", scopes).claim("tools", List.of())
                .claim("doc_scopes", List.of("public"))
                .issueTime(Date.from(now)).expirationTime(Date.from(now.plusSeconds(600)))
                .jwtID(UUID.randomUUID().toString());
        tweak.accept(b);
        return sign(b.build(), PostgresTestBase.DELEGATION_KEYS.getPrivate());
    }

    public static String sign(JWTClaimsSet claims, PrivateKey key) {
        try {
            SignedJWT jwt = new SignedJWT(new JWSHeader(JWSAlgorithm.ES256), claims);
            jwt.sign(new ECDSASigner((ECPrivateKey) key));
            return jwt.serialize();
        } catch (JOSEException e) {
            throw new IllegalStateException(e);
        }
    }

    public static String hs256(JWTClaimsSet claims, String secret) {
        try {
            SignedJWT jwt = new SignedJWT(new JWSHeader(JWSAlgorithm.HS256), claims);
            jwt.sign(new MACSigner(secret.getBytes()));
            return jwt.serialize();
        } catch (JOSEException e) {
            throw new IllegalStateException(e);
        }
    }
}
