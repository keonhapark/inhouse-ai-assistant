import type { ButtonHTMLAttributes } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'danger'

type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }

export function Button({ variant = 'secondary', className, type = 'button', ...rest }: Props) {
  const cls = ['btn', `btn--${variant}`, className].filter(Boolean).join(' ')
  return <button type={type} className={cls} {...rest} />
}
