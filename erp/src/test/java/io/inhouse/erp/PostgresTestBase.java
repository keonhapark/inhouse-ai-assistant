package io.inhouse.erp;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.GeneralSecurityException;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.spec.ECGenParameterSpec;
import java.util.Base64;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.PostgreSQLContainer;

/**
 * 시험 클래스들이 PostgreSQL 컨테이너 하나와 같은 스프링 문맥을 같이 씁니다.
 * 위임 토큰 시험용 ES256 키 쌍은 시험마다 새로 만들고, 공개 키만 파일로 erp에 줍니다.
 */
@SpringBootTest
@Import(PostgresTestBase.Containers.class)
public abstract class PostgresTestBase {

    public static final String JWT_SECRET = "test-only-secret-0123456789abcdef0123456789";
    public static final String DEMO_PASSWORD = "test-demo";
    public static final KeyPair DELEGATION_KEYS = ecKeys();
    private static final Path PUBLIC_KEY_FILE = writePublicKey(DELEGATION_KEYS);

    @TestConfiguration(proxyBeanMethods = false)
    public static class Containers {
        private static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:16-alpine");

        @Bean
        @ServiceConnection
        PostgreSQLContainer<?> postgres() {
            return POSTGRES;
        }
    }

    @DynamicPropertySource
    static void authProperties(DynamicPropertyRegistry r) {
        r.add("erp.jwt-secret", () -> JWT_SECRET);
        r.add("erp.demo-password", () -> DEMO_PASSWORD);
        r.add("erp.delegation-public-key", PUBLIC_KEY_FILE::toString);
    }

    private static KeyPair ecKeys() {
        try {
            KeyPairGenerator g = KeyPairGenerator.getInstance("EC");
            g.initialize(new ECGenParameterSpec("secp256r1"));
            return g.generateKeyPair();
        } catch (GeneralSecurityException e) {
            throw new IllegalStateException(e);
        }
    }

    private static Path writePublicKey(KeyPair keys) {
        try {
            Path f = Files.createTempFile("delegation-test", ".pub.pem");
            f.toFile().deleteOnExit();
            String b64 = Base64.getMimeEncoder(64, "\n".getBytes()).encodeToString(keys.getPublic().getEncoded());
            Files.writeString(f, "-----BEGIN PUBLIC KEY-----\n" + b64 + "\n-----END PUBLIC KEY-----\n");
            return f;
        } catch (IOException e) {
            throw new UncheckedIOException(e);
        }
    }
}
