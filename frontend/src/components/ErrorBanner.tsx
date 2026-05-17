interface Props {
  message: string
  onRetry?: () => void
}

export default function ErrorBanner({ message, onRetry }: Props) {
  return (
    <div className="flex items-center justify-between bg-red-50 border border-red-200 rounded p-4 text-sm text-red-700">
      <span>{message}</span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="ml-4 underline hover:no-underline shrink-0"
        >
          Retry
        </button>
      )}
    </div>
  )
}
