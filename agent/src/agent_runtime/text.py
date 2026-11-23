"""직원 화면 문구 도우미(#578, ux/copy-guide.md)."""

from __future__ import annotations


def josa(word: str, pair: str = "을를") -> str:
    """받침이 있으면 앞 글자(을·이·은), 없으면 뒤 글자(를·가·는). 영문·숫자로 끝나면 읽는 소리로 어림합니다."""
    if not word:
        return word
    ch = word[-1]
    if ch.isascii():
        has = ch.upper() in "0136789LMNR"
    else:
        has = 0xAC00 <= ord(ch) <= 0xD7A3 and (ord(ch) - 0xAC00) % 28 != 0
    return word + (pair[0] if has else pair[1])
