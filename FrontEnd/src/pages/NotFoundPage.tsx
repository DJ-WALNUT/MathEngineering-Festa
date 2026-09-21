import { Link } from 'react-router-dom'

import { Gamepad } from '../components/Decorations'

export default function NotFoundPage() {
  return (
    <div className="card mx-auto max-w-md p-10 text-center">
      <Gamepad className="mx-auto h-14 w-auto" />
      <p className="font-pixel mt-5 text-5xl text-brick-500">404</p>
      <h1 className="font-pixel mt-3 text-xl text-ink-900">GAME OVER — 페이지가 없어요</h1>
      <p className="mt-2 text-sm text-ink-600">주소를 다시 확인해 주세요.</p>
      <Link to="/" className="btn-primary mt-8">
        CONTINUE? 홈으로
      </Link>
    </div>
  )
}
