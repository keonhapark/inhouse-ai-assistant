package io.inhouse.erp.auth;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * @param jwtSecret            직원 JWT(HS256) 서명 키. 32바이트 이상. 비어 있으면 시작할 때 임의로 만듭니다(개발용)
 * @param jwtTtlSeconds        직원 JWT 유효 시간
 * @param demoPassword         데모 로그인 비밀번호(모든 직원 공통)
 * @param delegationPublicKey  gateway 위임 토큰(ES256) 공개 키 PEM 파일 경로. 비어 있으면 위임 토큰을 받지 않습니다
 */
@ConfigurationProperties(prefix = "erp")
public record AuthProperties(String jwtSecret, long jwtTtlSeconds, String demoPassword, String delegationPublicKey) {}
