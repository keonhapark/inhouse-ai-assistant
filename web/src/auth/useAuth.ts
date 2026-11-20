import { useContext } from 'react'
import { AuthContext, type AuthValue } from './context'

export function useAuth(): AuthValue {
  const v = useContext(AuthContext)
  if (!v) throw new Error('AuthProvider 밖에서 useAuth를 불렀습니다.')
  return v
}
