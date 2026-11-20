import type { HTMLAttributes, ReactNode } from 'react'

type Props = HTMLAttributes<HTMLElement> & {
  header?: ReactNode
  footer?: ReactNode
}

export function Card({ header, footer, children, className, ...rest }: Props) {
  return (
    <section className={['card', className].filter(Boolean).join(' ')} {...rest}>
      {header && <div className="card__header">{header}</div>}
      <div className="card__body">{children}</div>
      {footer && <div className="card__footer">{footer}</div>}
    </section>
  )
}
