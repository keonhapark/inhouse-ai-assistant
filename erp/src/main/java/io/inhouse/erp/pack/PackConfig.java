package io.inhouse.erp.pack;

import java.nio.file.Path;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class PackConfig {

    private static final Logger log = LoggerFactory.getLogger(PackConfig.class);

    /**
     * 팩을 읽고 단계보다 높은 stage의 양식은 끕니다. 꺼진 양식은 목록에 없고 상신·대결 범위에서 모르는
     * 양식(422)입니다. 단계는 pack.yaml의 stage이고, ERP_STAGE가 있으면 그것으로 덮어씁니다(agent·gateway와 같은 기준).
     */
    @Bean
    public Pack pack(@Value("${erp.pack-dir}") String dir, @Value("${erp.stage:}") String stage) {
        Pack all = PackLoader.load(Path.of(dir));
        boolean overridden = stage != null && !stage.isBlank();
        int max = overridden ? Integer.parseInt(stage.trim()) : all.stage();
        Pack pack = all.withFormsUpTo(max);
        log.info("erp 단계 {}({}): 켠 양식 {}", max, overridden ? "ERP_STAGE" : "pack.yaml",
                pack.forms().stream().map(Pack.FormDef::id).toList());
        return pack;
    }
}
