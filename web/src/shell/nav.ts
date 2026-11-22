import { Bot, Building2, ChartColumn, ClipboardCheck, FileCheck2, Globe, ScrollText, Sparkles, type LucideIcon } from 'lucide-react'
import type { Schemas } from '../api/client'

/**
 * 왼쪽 탐색 막대의 메뉴(ux/research/ia.md 2절). 업무·회사·운영 묶음이고, 운영은 감사 조회 역할만 봅니다.
 * 대결 설정 메뉴는 결재에서 떼어 내는 묶음(#557)에서 더합니다.
 */
export type NavItem = { to: string; label: string; icon: LucideIcon; end?: boolean }
export type NavGroup = { id: string; label: string; items: NavItem[]; visible?: (me: Schemas['Employee']) => boolean }

export const NAV: NavGroup[] = [
  {
    id: 'work',
    label: '업무',
    items: [
      { to: '/', label: 'AI 비서', icon: Sparkles, end: true },
      { to: '/approvals', label: '결재', icon: FileCheck2 },
    ],
  },
  {
    id: 'company',
    label: '회사',
    items: [
      { to: '/org', label: '조직도', icon: Building2 },
      { to: '/agents', label: 'AI 에이전트', icon: Bot },
    ],
  },
  {
    id: 'ops',
    label: '운영',
    visible: (me) => me.roles.includes('auditor'),
    items: [
      { to: '/ops/metrics', label: '운영 지표', icon: ChartColumn },
      { to: '/ops/egress', label: '외부 전송 기록', icon: Globe },
      { to: '/ops/audit', label: '감사 로그', icon: ScrollText },
      { to: '/ops/eval', label: '평가 리포트', icon: ClipboardCheck },
    ],
  },
]

export const navFor = (me: Schemas['Employee']) => NAV.filter((g) => !g.visible || g.visible(me))
