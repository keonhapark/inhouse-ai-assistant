import * as Menu from '@radix-ui/react-dropdown-menu'
import { Bell } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, type Schemas } from '../api/client'
import { formatWhen } from '../display/format'

type Props = {
  title: string
  titleId?: string
  /** 제목 옆 보조 글(담당 AI 등) */
  sub?: ReactNode
  /** 보조 글 뒤에 붙는 것(세그먼트 컨트롤 등) */
  children?: ReactNode
}

/** 화면 머리(ux/design-system.md 3.1): 제목 + 보조 글 … 오른쪽 알림. 높이 52px */
export function Toolbar({ title, titleId, sub, children }: Props) {
  return (
    <header className="toolbar">
      <h1 id={titleId} className="toolbar__title">
        {title}
      </h1>
      {sub && <span className="toolbar__sub">{sub}</span>}
      {children}
      <span className="toolbar__spacer" />
      <NotificationBell />
    </header>
  )
}

type Notification = Schemas['Notification']

/** 알림 메뉴. 안 읽은 알림이 있으면 종에 빨간 점을 붙입니다. 결재 알림을 고르면 결재 화면으로 갑니다 */
export function NotificationBell() {
  const navigate = useNavigate()
  const [items, setItems] = useState<Notification[] | null>(null)
  const [failed, setFailed] = useState(false)
  useEffect(() => {
    let alive = true
    api.GET('/notifications').then(
      ({ data }) => alive && (data ? setItems(data.items) : setFailed(true)),
      () => alive && setFailed(true),
    )
    return () => {
      alive = false
    }
  }, [])
  const unread = items?.filter((n) => !n.read).length ?? 0
  return (
    <Menu.Root>
      <Menu.Trigger className="icon-btn toolbar__bell" aria-label={unread ? `알림, 새 알림 ${unread}건` : '알림'}>
        <Bell aria-hidden />
        {unread > 0 && <span className="toolbar__dot" aria-hidden />}
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content className="menu notifications" align="end" sideOffset={6}>
          <Menu.Label className="menu__label">알림</Menu.Label>
          {failed ? (
            <p className="notifications__empty">알림을 불러오지 못했습니다.</p>
          ) : !items?.length ? (
            <p className="notifications__empty">새 알림이 없습니다.</p>
          ) : (
            items.map((n) => (
              <Menu.Item key={n.id} className="menu__item notifications__item" onSelect={() => navigate('/approvals')}>
                <span>{n.message}</span>
                <span className="notifications__when">{formatWhen(n.createdAt)}</span>
              </Menu.Item>
            ))
          )}
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  )
}
