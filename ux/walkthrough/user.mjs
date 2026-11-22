// 과업 걸어 보기에서 사람의 조작을 대신하는 얇은 층입니다.
// 화면에 보이는 이름(역할·라벨)으로만 요소를 찾고, 클릭·입력·키 수와 단계를 셉니다.
// 요소를 못 찾으면 그 자리를 "막힘"으로 남기고 과업을 멈춥니다.

export class Blocked extends Error {
  constructor(step, cause) {
    super(`막힘: ${step}`)
    this.step = step
    this.cause = cause
  }
}

export class User {
  constructor(page, { shotDir, taskId, timeoutMs = 5000 }) {
    this.page = page
    this.shotDir = shotDir
    this.taskId = taskId
    this.timeoutMs = timeoutMs
    this.steps = []
    this.counts = { clicks: 0, fields: 0, chars: 0, keys: 0, files: 0 }
    this.shots = []
  }

  async #act(kind, label, loc, fn) {
    const t0 = Date.now()
    try {
      await loc.first().waitFor({ state: 'visible', timeout: this.timeoutMs })
      await fn(loc.first())
    } catch (err) {
      this.steps.push({ kind, label, ok: false, ms: Date.now() - t0 })
      throw new Blocked(label, err)
    }
    this.steps.push({ kind, label, ok: true, ms: Date.now() - t0 })
  }

  click(loc, label) {
    return this.#act('click', label, loc, async (l) => {
      await l.click()
      this.counts.clicks++
    })
  }

  /** 체크박스·라디오도 사람에게는 클릭 한 번입니다. */
  check(loc, label, on = true) {
    return this.#act('click', label, loc, async (l) => {
      await l.setChecked(on)
      this.counts.clicks++
    })
  }

  fill(loc, text, label) {
    return this.#act('fill', label, loc, async (l) => {
      await l.fill(text)
      this.counts.fields++
      this.counts.chars += text.length
    })
  }

  select(loc, option, label) {
    return this.#act('select', label, loc, async (l) => {
      await l.selectOption({ label: option })
      this.counts.clicks += 2 // 펼치기 + 고르기
    })
  }

  press(loc, key, label) {
    return this.#act('key', label, loc, async (l) => {
      await l.press(key)
      this.counts.keys++
    })
  }

  /** 첨부 버튼을 눌러 파일 고르기 창에서 파일을 고릅니다(클릭 1 + 파일 1). */
  upload(loc, files, label) {
    return this.#act('upload', label, loc, async (l) => {
      const chooser = this.page.waitForEvent('filechooser', { timeout: this.timeoutMs })
      await l.click()
      ;(await chooser).setFiles(files)
      this.counts.clicks++
      this.counts.files += files.length
    })
  }

  /** 눈으로 찾는 단계입니다. 조작 수는 늘지 않지만 단계로 셉니다. */
  see(loc, label, timeoutMs = this.timeoutMs) {
    return this.#act('see', label, loc, (l) => l.waitFor({ state: 'visible', timeout: timeoutMs }))
  }

  async shot(name) {
    const file = `${this.taskId}-${String(this.shots.length + 1).padStart(2, '0')}-${name}.jpg`
    await this.page.screenshot({ path: `${this.shotDir}/${file}`, type: 'jpeg', quality: 70 })
    this.shots.push(file)
  }
}
