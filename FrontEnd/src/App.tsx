import { Route, Routes } from 'react-router-dom'

import Layout from './components/Layout'
import CheckInPage from './pages/CheckInPage'
import DrawPage from './pages/DrawPage'
import HomePage from './pages/HomePage'
import SchedulePage from './pages/SchedulePage'
import NotFoundPage from './pages/NotFoundPage'
import PaymentPage from './pages/PaymentPage'
import PersonalCardPage from './pages/PersonalCardPage'
import AdminPage from './pages/admin/AdminPage'

// 타임테이블은 화면이 다 되어 있지만 내용이 확정되기 전이라 아직 알리지 않는다.
// 주소를 아는 사람만 들어올 수 있게 길은 열어 두고, 메뉴에서만 뺐다 (data/event.ts 의 NAV_LINKS).
// 공개할 때는 그 한 줄을 되살리면 된다. 여기는 손댈 것이 없다.
//
// 장소 안내는 이번 행사에 없다. 당일 한 곳에서 끝나 지도와 길찾기가 쓰이지 않는다.

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<HomePage />} />
        <Route path="schedule" element={<SchedulePage />} />
        <Route path="payment" element={<PaymentPage />} />
        {/* 입구 QR 로만 들어오는 화면이라 네비게이션에는 넣지 않는다. */}
        <Route path="checkin" element={<CheckInPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
      {/*
        개인 카드. 명찰의 QR 이 가리키는 화면이라 공개 레이아웃(네비게이션)을 쓰지
        않는다 — 문 앞에서 열어 그대로 내미는 화면이므로 QR 이 가장 위에 와야 한다.
      */}
      <Route path="/p/:token" element={<PersonalCardPage />} />
      {/* 관리자 화면은 공개 레이아웃(네비게이션)을 쓰지 않는다. */}
      <Route path="/admin" element={<AdminPage />} />
      {/*
        럭키드로우 추첨 화면. 프로젝터에 띄우는 전체 화면 연출이라 관리자 헤더를
        쓰지 않지만, **관리자 하위 경로**이고 인증도 관리자와 같은 것을 쓴다
        (pages/admin/AdminSession.tsx). 주소를 알아냈다고 열리지 않는다.
      */}
      <Route path="/admin/draw" element={<DrawPage />} />
    </Routes>
  )
}
