/**
 * Render the small subset of Markdown used in curated factor and evidence prose:
 * `**bold**` spans and single newlines (`\n` → `<br>`).
 *
 * Curated fields such as `scoring_methodology` and `evidence_summary` are authored
 * with `**Label**` section headers and inline `**Protocol Name**` emphasis. They were
 * previously rendered as raw text, so the asterisks leaked into the page. The site's
 * existing CSS already styles `.body p strong`, so the intended output is `<strong>`.
 *
 * Input is trusted (our own DB-generated content) but we HTML-escape first so stray
 * `<`, `>`, or `&` in prose can never inject markup when used with `set:html`.
 *
 * `italics` is opt-in and OFF by default. Single-asterisk emphasis is only safe to
 * convert in prose that does not also use `*` as a multiplication operator. Factor
 * `scoring_methodology` is clean prose, but protocol `evidence_summary` mixes
 * `*italic*` with code/math like `balance() * 1e18`, so callers rendering evidence
 * must leave `italics` off and keep those asterisks literal.
 */
export function inlineMarkdown(
  input: string | null | undefined,
  opts: { italics?: boolean } = {},
): string {
  if (!input) return '';
  let out = input
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
  out = out.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  if (opts.italics) {
    // Only match when the asterisks hug non-space text on a single line (real
    // `*italic*`), never ` * ` (multiplication) or `*` used as a list/separator
    // marker; the `\n` exclusion stops a stray pair spanning multiple lines.
    out = out.replace(/(?<!\*)\*(\S(?:[^*\n]*\S)?)\*(?!\*)/g, '<em>$1</em>');
  }
  return out.replace(/\n/g, '<br>');
}
