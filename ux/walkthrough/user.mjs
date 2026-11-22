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

  // 이름이 같은 요소가 둘 이상이면 어느 것을 누를지 모르므로 막힘으로 봅니다(재설계 뒤 조용히 다른 것을 누르지 않게).
  async #act(kind, label, loc, fn, timeoutMs = this.timeoutMs) {
    const t0 = Date.now()
    try {
      await loc.first().waitFor({ state: 'visible', timeout: timeoutMs })
      const n = await loc.count()
      if (n > 1 && kind !== 'see') throw new Error(`같은 이름의 요소가 ${n}개입니다`)
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

  /** 체크박스·라디오도 사람에게는 클릭 한 번입니다. 이미 원하는 상태면 누르지 않고 세지 않습니다. */
  check(loc, label, on = true) {
    return this.#act('click', label, loc, async (l) => {
      if ((await l.isChecked()) === on) return
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
      const [chooser] = await Promise.all([this.page.waitForEvent('filechooser', { timeout: this.timeoutMs }), l.click()])
      await chooser.setFiles(files)
      this.counts.clicks++
      this.counts.files += files.length
    })
  }

  /** 눈으로 찾는 단계입니다. 조작 수는 늘지 않지만 단계로 셉니다. */
  see(loc, label, timeoutMs = this.timeoutMs) {
    return this.#act('see', label, loc, async () => {}, timeoutMs)
  }

  /** 조작 단계 수입니다. 눈으로 찾는 단계(see)는 스크립트마다 넣는 수가 달라 과업끼리 견줄 때 뺍니다. */
  get actions() {
    return this.steps.filter((s) => s.kind !== 'see').length
  }

  async shot(name) {
    const file = `${this.taskId}-${String(this.shots.length + 1).padStart(2, '0')}-${name}.jpg`
    await this.page.screenshot({ path: `${this.shotDir}/${file}`, type: 'jpeg', quality: 70 })
    this.shots.push(file)
  }
}
