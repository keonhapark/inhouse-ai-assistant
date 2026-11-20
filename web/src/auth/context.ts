import { createContext } from 'react'
import type { Employee } from '../api/client'

export type AuthState =
  | { status: 'loading' }
  | { status: 'anonymous' }
  | { status: 'signed-in'; employee: Employee }

export type AuthValue = {
  state: AuthState
  login(employeeNo: string, password: string): Promise<{ ok: true } | { ok: false; message: string }>
  logout(): void
}

export const AuthContext = createContext<AuthValue | null>(null)
