package io.inhouse.erp.common;

import io.inhouse.erp.pack.Pack;
import java.time.Clock;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class ClockConfig {

    /** 팩의 시간대(company.timezone) 시계. 시험에서 바꿔 끼울 수 있게 빈으로 둡니다. */
    @Bean
    public Clock clock(Pack pack) {
        return Clock.system(pack.timezone());
    }
}
