package io.inhouse.erp.common;

import io.inhouse.erp.auth.ScopeGuard;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final ScopeGuard scopeGuard;

    public WebConfig(ScopeGuard scopeGuard) {
        this.scopeGuard = scopeGuard;
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(scopeGuard);
    }
}
