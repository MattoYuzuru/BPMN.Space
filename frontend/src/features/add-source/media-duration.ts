/** Длительность и видеодорожка записи из метаданных браузера (до загрузки на сервер). */
export interface MediaFileInfo {
  durationSec: number
  hasVideo: boolean
}

const VIDEO_EXTENSIONS = /\.(mp4|mov|mkv|webm)$/i

export function mediaFileInfo(
  file: File,
  createElement: (tag: 'audio' | 'video') => HTMLMediaElement = (tag) =>
    document.createElement(tag) as HTMLMediaElement,
): Promise<MediaFileInfo> {
  const hasVideoByType = file.type.startsWith('video/') || VIDEO_EXTENSIONS.test(file.name)
  return new Promise((resolve) => {
    const element = createElement(hasVideoByType ? 'video' : 'audio')
    const url = URL.createObjectURL(file)
    const finish = (info: MediaFileInfo) => {
      URL.revokeObjectURL(url)
      resolve(info)
    }
    element.preload = 'metadata'
    element.onloadedmetadata = () =>
      finish({
        durationSec: Number.isFinite(element.duration) ? Math.max(0, element.duration) : 0,
        hasVideo: hasVideoByType,
      })
    element.onerror = () => finish({ durationSec: 0, hasVideo: hasVideoByType })
    element.src = url
  })
}
