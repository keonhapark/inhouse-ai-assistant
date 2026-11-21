package io.inhouse.erp.pack;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/** 켜는 양식의 단계는 pack.yaml stage가 기준이고, ERP_STAGE는 덮어쓰기만 합니다. */
class PackConfigTest {

    private static final Path PACK = Path.of("../packs/manufacturing");

    /** 제조 팩을 복사하고 pack.yaml의 stage만 바꿉니다. */
    private static Path packWithStage(Path tmp, String stageLine) throws IOException {
        try (Stream<Path> files = Files.walk(PACK)) {
            for (Path src : files.toList()) {
                Path dst = tmp.resolve(PACK.relativize(src).toString());
                if (Files.isDirectory(src)) {
                    Files.createDirectories(dst);
                } else {
                    Files.copy(src, dst);
                }
            }
        }
        Path yaml = tmp.resolve("pack.yaml");
        Files.writeString(yaml, Files.readString(yaml).replaceFirst("(?m)^stage: \\d+$", stageLine));
        return tmp;
    }

    private static Stream<String> formIds(Pack p) {
        return p.forms().stream().map(Pack.FormDef::id);
    }

    @Test
    void stageComesFromPackYamlWhenNoOverride(@TempDir Path tmp) throws IOException {
        Pack p = new PackConfig().pack(packWithStage(tmp, "stage: 1").toString(), "");
        assertThat(formIds(p)).containsExactly("leave");
    }

    @Test
    void erpStageOverridesPackYaml(@TempDir Path tmp) throws IOException {
        String dir = packWithStage(tmp, "stage: 1").toString();
        assertThat(formIds(new PackConfig().pack(dir, "2"))).containsExactly("leave", "expense", "purchase");
        assertThat(formIds(new PackConfig().pack(PACK.toString(), "1"))).containsExactly("leave");
        assertThat(formIds(new PackConfig().pack(PACK.toString(), null))).containsExactly("leave", "expense", "purchase");
    }

    @Test
    void packWithoutStageStopsStartup(@TempDir Path tmp) throws IOException {
        String dir = packWithStage(tmp, "").toString();
        assertThatThrownBy(() -> new PackConfig().pack(dir, "")).isInstanceOf(IllegalStateException.class);
    }

    @Test
    void erpRolesComeFromOrgYamlOrDefault(@TempDir Path tmp) throws IOException {
        assertThat(PackLoader.load(PACK).erpRoles()).isEqualTo(new Pack.ErpRoles("hr_staff", "auditor", "it_admin", "quality_staff", "sales_staff"));
        Path dir = packWithStage(tmp, "stage: 2");
        Path org = dir.resolve("org.yaml");
        String text = Files.readString(org);
        Files.writeString(org, text.replace("  hr: hr_staff\n", "  hr: people_ops\n"));
        assertThat(PackLoader.load(dir).erpRoles()).isEqualTo(new Pack.ErpRoles("people_ops", "auditor", "it_admin", "quality_staff", "sales_staff"));
        Files.writeString(org, text.replaceFirst("(?m)^erp_roles:\n(  .*\n)+", ""));
        assertThat(PackLoader.load(dir).erpRoles()).isEqualTo(Pack.ErpRoles.DEFAULT);
    }
}
