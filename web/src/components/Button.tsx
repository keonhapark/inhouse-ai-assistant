import type { ButtonHTMLAttributes, Ref } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'danger'

// React 19부터 ref는 일반 속성으로 넘어옵니다(포커스를 옮길 때 씀).
type Props = ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant; ref?: Ref<HTMLButtonElement> }

export function Button({ variant = 'secondary', className, type = 'button', ...rest }: Props) {
  const cls = ['btn', `btn--${variant}`, className].filter(Boolean).join(' ')
  return <button type={type} className={cls} {...rest} />
}
