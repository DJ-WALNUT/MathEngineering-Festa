import { InstagramIcon, KakaoIcon } from './Decorations'
import { EVENT } from '../data/event'

const STYLE = {
  kakao: {
    className: 'bg-gold-400 text-ink-900 hover:bg-gold-300',
    Icon: KakaoIcon,
  },
  instagram: {
    className: 'bg-white text-heart-500 hover:bg-heart-100',
    Icon: InstagramIcon,
  },
} as const

/**
 * 학생회 상시 문의 창구.
 *
 * 담당자 개인 번호 대신 채널로 안내한다. 담당자가 바뀌어도 사이트를 고칠 필요가 없고,
 * 문의가 한곳에 모여 놓치지 않는다.
 *
 * 이번 행사는 **두 학생회(이과대 · 공과대)가 함께 열어 인스타그램이 둘이다.**
 * 채널 종류가 같으면 이름표('인스타그램')만으로는 구별이 안 되므로, 접힌
 * 모양에서도 계정 이름(@cuk_ns)을 쓴다. 이름표 두 개가 같은 문구로 나란히 서면
 * 같은 버튼이 두 번 있는 것처럼 보인다.
 *
 * 접힌 모양은 좁은 화면에서 **한 줄에 하나씩 세로로 쌓고**, 넓어지면 가로로 편다.
 * 알약 두 개를 줄바꿈에 맡겨 두면 폰에서 하나는 왼쪽, 하나는 다음 줄 가운데에
 * 걸쳐 어긋난 계단처럼 보인다.
 */
export default function ContactChannels({ compact = false }: { compact?: boolean }) {
  return (
    <div
      className={
        compact
          ? 'flex flex-col items-stretch gap-2 sm:flex-row sm:flex-wrap sm:items-center sm:justify-center'
          : 'grid gap-3 sm:grid-cols-2'
      }
    >
      {EVENT.contacts.map((channel) => {
        const style = STYLE[channel.kind]
        return (
          <a
            key={channel.url}
            href={channel.url}
            target="_blank"
            rel="noreferrer noopener"
            className={
              compact
                ? `inline-flex items-center justify-center gap-1.5 rounded-md border-2 border-ink-900 px-3.5 py-1.5 text-xs font-bold shadow-[2px_2px_0_var(--color-ink-900)] transition ${style.className}`
                : `flex items-center gap-3 rounded-md border-2 border-ink-900 px-4 py-3.5 shadow-[3px_3px_0_var(--color-ink-900)] transition ${style.className}`
            }
          >
            <style.Icon className={compact ? 'size-4 shrink-0' : 'size-6 shrink-0'} />
            {compact ? (
              <span className="min-w-0 truncate">
                <span className="font-pixel-small">{channel.handle}</span>
                <span className="ml-1.5 font-semibold opacity-70">{channel.label}</span>
              </span>
            ) : (
              <span className="min-w-0">
                <span className="block text-sm font-black">{channel.label}</span>
                <span className="font-pixel-small block truncate text-xs opacity-80">
                  {channel.handle}
                </span>
              </span>
            )}
          </a>
        )
      })}
    </div>
  )
}
