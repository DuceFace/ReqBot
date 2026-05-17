export default function LoadingSpinner() {
  return (
    <div className="flex justify-center py-12" aria-label="Loading">
      <div className="w-8 h-8 border-4 border-blue-600 border-t-transparent rounded-full animate-spin" />
    </div>
  )
}
