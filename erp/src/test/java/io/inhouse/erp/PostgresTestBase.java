package io.inhouse.erp;

import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.springframework.context.annotation.Bean;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Import;
import org.testcontainers.containers.PostgreSQLContainer;

/** 시험 클래스들이 PostgreSQL 컨테이너 하나를 같이 씁니다. */
@SpringBootTest
@Import(PostgresTestBase.Containers.class)
public abstract class PostgresTestBase {

    @TestConfiguration(proxyBeanMethods = false)
    public static class Containers {
        private static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:16-alpine");

        @Bean
        @ServiceConnection
        PostgreSQLContainer<?> postgres() {
            return POSTGRES;
        }
    }
}
