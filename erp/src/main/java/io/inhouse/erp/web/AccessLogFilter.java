package io.inhouse.erp.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * 요청마다 한 줄 접근 로그(메서드, 경로, 상태, 걸린 ms). 5xx나 1초 넘게 걸린 요청은 WARN입니다.
 * 장애 분석(incident/)이 로그만으로 증상 구간을 찾을 수 있게 둡니다. 질의 문자열과 토큰은 남기지 않습니다.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class AccessLogFilter extends OncePerRequestFilter {

    static final long SLOW_MS = 1000;
    private static final Logger log = LoggerFactory.getLogger("access");

    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
            throws ServletException, IOException {
        long started = System.nanoTime();
        int status = 500;
        try {
            chain.doFilter(req, res);
            status = res.getStatus();
        } finally {
            long ms = (System.nanoTime() - started) / 1_000_000;
            String line = "{} {} {} {}ms";
            if (status >= 500 || ms >= SLOW_MS) {
                log.warn(line, req.getMethod(), req.getRequestURI(), status, ms);
            } else {
                log.info(line, req.getMethod(), req.getRequestURI(), status, ms);
            }
        }
    }
}
