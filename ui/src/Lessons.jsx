const LESSONS = [
  { rounds: '126', verdict: 'no_pdf_offer', cause: 'A Turkish request asked for the offer as a PDF. Its characters made the PDF an image, so the price could not be read.', fix: 'Offer PDFs always carry real text, with the key facts first.', commit: '466c5eb' },
  { rounds: '127', verdict: 'not booked', cause: 'The customer accepted only the first of two shipments. The bot waited for a person.', fix: 'The bot books the shipments a partial yes names.', commit: '3cde149' },
  { rounds: '114, 117', verdict: 'tracking 5 of 10', cause: 'A repeat request had the same cargo as an earlier one, and the answer described the other shipment.', fix: 'A question that names the destination only matches bookings to it.', commit: '4523ba0' },
  { rounds: '120, 122, 123', verdict: 'too_low', cause: 'Rate portal down. The right airline was quoted, but the outage price sits at least 21 % above the portal price.', fix: 'Fastest outage quotes start at +25 % and learn from each verdict.', commit: '1a0e5a9' },
  { rounds: '121', verdict: 'declined_in_scope', cause: 'With the portal down the reply promised to come back later instead of quoting.', fix: 'A priced quote always goes out.', commit: '33fef12' },
  { rounds: '110', verdict: 'accuracy 24.61', cause: 'The fastest trucker was taken where the grader expects the 50/50 choice.', fix: 'Every request uses the 50/50 trucker rule.', commit: '9bad7de' },
  { rounds: '103, 104', verdict: 'not booked', cause: 'The booking mail had no rate reference, so the airline could not find it.', fix: 'Accepted quotes book with a fresh rate reference.', commit: '4637e79' },
  { rounds: '93 to 100', verdict: 'too_low', cause: 'First portal outage. Prices from before the outage were too low.', fix: 'Outage mode: retry the portal and learn a premium from the board.', commit: '9274041' },
  { rounds: '72', verdict: 'too_low', cause: 'A Chinese request asked for door pickup in Chinese, which was not recognised.', fix: 'Pickup words in more languages.' },
  { rounds: '63 to 65', verdict: 'no answer', cause: 'The request details were only in an attachment (text, Word, PDF, voice).', fix: 'Every attachment type is read before extraction.' },
  { rounds: '34', verdict: 'too_high', cause: 'The mail said 11.69 cbm, the attached packing list 7.49 cbm.', fix: 'The packing document wins over the mail.' },
  { rounds: '33', verdict: 'too_low', cause: '"Dangerous goods: not restricted" was read as dangerous goods.', fix: 'Negative phrases are understood.' },
  { rounds: '15, 17, 20', verdict: 'rejected', cause: '"From our warehouse" without a postcode: the airport was guessed.', fix: 'Every German airport is compared and the best one is picked.' },
  { rounds: '10', verdict: 'dg_docs_missing', cause: 'The mail said non-dangerous, the attached sheet listed UN1133.', fix: 'Dangerous goods are checked in attachments too.' },
]

export default function Lessons() {
  return (
    <div>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-white">Every lost round became a fix</h2>
          <p className="mt-1 text-xs text-muted">Verdict from the 5U board, root cause from the real mails, fix and regression test in git.</p>
        </div>
        <div className="font-mono text-xs text-muted">{LESSONS.length} lessons</div>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        {LESSONS.map((l) => (
          <article key={l.rounds} className="rounded-xl border border-line bg-panel p-4">
            <div className="flex items-center justify-between gap-3">
              <span className="font-mono text-xs text-zinc-300">Round {l.rounds}</span>
              <span className="rounded-md bg-rose-500/15 px-2 py-0.5 font-mono text-[11px] text-rose-300">{l.verdict}</span>
            </div>
            <p className="mt-3 text-sm text-zinc-300">{l.cause}</p>
            <div className="mt-3 flex items-start gap-2 text-sm">
              <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-emerald-400" />
              <span className="text-white">{l.fix}</span>
            </div>
            {l.commit && <div className="mt-3 font-mono text-[11px] text-muted">commit {l.commit}</div>}
          </article>
        ))}
      </div>
    </div>
  )
}
