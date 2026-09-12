import { useIsFetching } from '@tanstack/react-query'

/** Ein duenner Lichtstreifen unter der Kopfzeile, solange etwas geladen wird. */
export function LoadingBar() {
  const fetching = useIsFetching()
  if (!fetching) return null
  return (
    <div className="absolute inset-x-0 bottom-0 h-0.5 overflow-hidden" aria-hidden="true">
      <div className="h-full w-1/3 bg-accent-500 animate-nv-sweep" />
    </div>
  )
}
