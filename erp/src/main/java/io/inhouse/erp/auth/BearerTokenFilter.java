package io.inhouse.erp.auth;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.inhouse.erp.common.ApiException;
import io.inhouse.erp.common.Problems;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.List;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/** Authorization: Bearer 토큰을 확인해 {@link ErpPrincipal}을 보안 문맥에 둡니다. 틀린 토큰은 바로 401입니다. */
public class BearerTokenFilter extends OncePerRequestFilter {

    private final TokenService tokens;
    private final ObjectMapper mapper;

    public BearerTokenFilter(TokenService tokens, ObjectMapper mapper) {
        this.tokens = tokens;
        this.mapper = mapper;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest req, HttpServletResponse res, FilterChain chain)
            throws ServletException, IOException {
        String header = req.getHeader("Authorization");
        if (header != null && header.regionMatches(true, 0, "Bearer ", 0, 7)) {
            try {
                ErpPrincipal p = tokens.authenticate(header.substring(7).trim());
                SecurityContextHolder.getContext().setAuthentication(
                        UsernamePasswordAuthenticationToken.authenticated(p, null, List.of()));
            } catch (ApiException e) {
                SecurityContextHolder.clearContext();
                Problems.write(res, mapper, e.status(), e.code(), e.detail());
                return;
            }
        }
        chain.doFilter(req, res);
    }
}
