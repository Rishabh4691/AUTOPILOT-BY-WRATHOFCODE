/** The home page's light behind a page: a breathing orange glow and a faint grid. */
export default function PageBackdrop() {
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 -z-10">
      <div className="lb-aurora absolute top-[-10vh] left-1/2 h-[70vh] w-[90vw] -translate-x-1/2 rounded-[50%] blur-[90px]" />
      <div className="lb-grid absolute inset-0" />
    </div>
  )
}
