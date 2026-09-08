export default function LoadingSpinner({ message = 'Loading…' }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-3 text-gray-500">
      <svg
        className="animate-spin h-8 w-8 text-brand-600"
        xmlns="http://www.w3.org/2000/svg"
        fill="none"
        viewBox="0 0 24 24"
      >
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path
          className="opacity-75"
          fill="currentColor"
          d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
        />
      </svg>
      <span className="text-sm">{message}</span>
    </div>
  );
}
