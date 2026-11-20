package io.inhouse.erp.pack;

import java.nio.file.Path;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class PackConfig {

    @Bean
    public Pack pack(@Value("${erp.pack-dir}") String dir) {
        return PackLoader.load(Path.of(dir));
    }
}
