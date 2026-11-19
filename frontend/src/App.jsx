import { useEffect, useState } from 'react'
import { BrowserRouter, Navigate, NavLink, Route, Routes } from 'react-router-dom'
import Today from './pages/Today'
import Patients from './pages/Patients'
import Consultation from './pages/Consultation'
import Prescriptions from './pages/Prescriptions'
import Account from './pages/Account'
import Staff from './pages/Staff'
import './App.css'
import StaffRegister from './pages/StaffRegister'
import ChatPopup from './pages/ChatPopup'

const menus = [
  { name: '오늘의 업무', path: '/today' },
  { name: '환자 관리', path: '/patients' },
  { name: '진료·상담', path: '/consultation' },
  { name: '처방 관리', path: '/prescriptions' },
  { name: '소통·계정', path: '/account' },
  { name: '직원 관리', path: '/staff' },
]
const roleMenus = {
  director: ['/today', '/patients', '/consultation', '/prescriptions', '/account', '/staff'],
  doctor: ['/today', '/patients', '/consultation', '/prescriptions', '/account'],
  desk: ['/today', '/patients', '/prescriptions', '/account'],
}
const getRole = (account) =>
  account?.isOwner ? 'director' :
  account?.role === 'DOCTOR' ? 'doctor' :
  account?.role === 'DESK' ? 'desk' : null

function Login({ onLogin }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail || '로그인에 실패했습니다.')
      onLogin(data.account)
    } catch (err) {
      setError(err.message || '서버 연결에 실패했습니다.')
    } finally {
      setSubmitting(false)
    }
  }
  return (
    <div style={{ maxWidth: 420, margin: '80px auto', padding: 30, background: 'white', borderRadius: 12 }}>
      <h1>한의결 로그인</h1>
      <p>등록된 직원 계정으로 로그인해 주세요.</p>
      <form onSubmit={submit} style={{ display: 'grid', gap: 12 }}>
        <label>이메일<input type="email" required value={email} onChange={e => setEmail(e.target.value)} style={{ display:'block', width:'100%', padding:10 }}/></label>
        <label>비밀번호<input type="password" required value={password} onChange={e => setPassword(e.target.value)} style={{ display:'block', width:'100%', padding:10 }}/></label>
        {error && <p role="alert" style={{color:'crimson'}}>{error}</p>}
        <button type="submit" disabled={submitting}>{submitting ? '로그인 중...' : '로그인'}</button>
      </form>
    </div>
  )
}

export default function App() {
  const [serverStatus, setServerStatus] = useState('확인 중')
  const [account, setAccount] = useState(null)
  const [authLoading, setAuthLoading] = useState(true)
  const currentRole = getRole(account)
  const openChatWindow = () => {
  const width = 420
  const height = 600

  const left = Math.max(0, window.screenX + window.outerWidth - width - 40)
  const top = Math.max(0, window.screenY + 80)

  const chatWindow = window.open(
    '/chat',
    'hanui_staff_chat',
    `popup=yes,width=${width},height=${height},left=${left},top=${top},resizable=yes,scrollbars=yes`
  )

  if (chatWindow) {
    chatWindow.focus()
  } else {
    alert('채팅창이 차단되었습니다. 브라우저의 팝업 허용 설정을 확인해 주세요.')
  }
}

  useEffect(() => {
    let active = true
    fetch('/api/health')
      .then(r => { if (!r.ok) throw new Error(); return r.json() })
      .then(data => { if (active) setServerStatus(data.status === 'ok' ? '연결됨' : '오류') })
      .catch(() => { if (active) setServerStatus('연결 실패') })
    fetch('/api/auth/me', { credentials: 'include' })
      .then(r => { if (!r.ok) throw new Error(); return r.json() })
      .then(data => { if (active) setAccount(data) })
      .catch(() => { if (active) setAccount(null) })
      .finally(() => { if (active) setAuthLoading(false) })
    return () => { active = false }
  }, [])

  const logout = async () => {
    try {
      const response = await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' })
      if (!response.ok) throw new Error('로그아웃 실패')
      setAccount(null)
    } catch (err) {
      alert(err.message)
    }
  }
  const visibleMenus = menus.filter(menu => (roleMenus[currentRole] || []).includes(menu.path))
  return (
  <BrowserRouter>
    {window.location.pathname === '/chat' ? (
      <ChatPopup />
    ) : (
      <div className="app-layout">
        {currentRole && (
          <aside className="sidebar">
            <div className="sidebar-logo"><h1>한의결</h1><p>한의사 처방 검토 지원 서비스</p></div>
            <nav className="sidebar-menu">
              {visibleMenus.map(menu => <NavLink key={menu.path} to={menu.path} className={({isActive}) => isActive ? 'menu-item active' : 'menu-item'}>{menu.name}</NavLink>)}
            </nav>
          </aside>
        )}
        <div className="main-layout">
          <header className="topbar">
            <span>한의결 관리 시스템</span>
            <span className="server-status">FastAPI: {serverStatus} {currentRole && <button onClick={logout} style={{marginLeft:16}}>로그아웃</button>}</span>
          </header>

          <main className="main-content">
            {authLoading ? (
              <p>로그인 상태 확인 중...</p>
            ) : window.location.pathname === '/staff/register' ? (
              <StaffRegister />
            ) : !currentRole ? (
              <Login onLogin={setAccount} />
            ) : (
              <Routes>
                <Route path="/" element={<Navigate to="/today" replace />} />
                <Route
                  path="/today"
                  element={
                    <Today
                      currentRole={currentRole}
                      onOpenChat={openChatWindow}
                    />
                  }
                />
                <Route path="/patients" element={<Patients currentRole={currentRole} />} />

                <Route
                  path="/consultation"
                  element={
                    currentRole !== 'desk'
                      ? <Consultation />
                      : <Navigate to="/today" replace />
                  }
                />

                <Route path="/prescriptions" element={<Prescriptions currentRole={currentRole} />} />
                <Route
                  path="/prescription/new"
                  element={
                    currentRole !== 'desk'
                      ? <Prescriptions currentRole={currentRole} />
                      : <Navigate to="/today" replace />
                  }
                />
                <Route
                  path="/account"
                  element={
                    <Account
                      currentRole={currentRole}
                      onOpenChat={openChatWindow}
                    />
                  }
                />
                <Route
                  path="/staff"
                  element={
                    currentRole === 'director'
                      ? <Staff />
                      : <Navigate to="/today" replace />
                  }
                />
                <Route path="*" element={<Navigate to="/today" replace />} />
              </Routes>
            )}
          </main>
        </div>
      </div>
      )}
    </BrowserRouter>
  )
  }
