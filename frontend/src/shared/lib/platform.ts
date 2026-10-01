/** Платформа пользователя: от неё зависят подписи клавиш (⌘ или Ctrl). */
export function isMacPlatform(): boolean {
  if (typeof navigator === 'undefined') return false
  const nav = navigator as Navigator & { userAgentData?: { platform?: string } }
  const platform = nav.userAgentData?.platform ?? nav.platform ?? ''
  return /mac|iphone|ipad/i.test(platform)
}
