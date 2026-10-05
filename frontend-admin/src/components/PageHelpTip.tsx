import { useAdminStore } from "../hooks/useAdminStore";
import { pageHelp, type PageHelpId } from "../services/pageHelp";
import { InfoTip } from "./InfoTip";

/**
 * The "i" beside a page title: what the page is, who it is for, what to do.
 *
 * It reads the role from the store rather than taking it as a prop. Every
 * page would otherwise have to pass down something it may not hold itself,
 * and a page that passed the wrong one would explain an owner's screen in an
 * admin's words with nothing to notice it.
 */
export function PageHelpTip({ page }: { page: PageHelpId }) {
  const { role } = useAdminStore();
  // Signed out there is no page to explain; the owner's words are the
  // narrower claim for the moment in between.
  const help = pageHelp(page, role ?? "OWNER");

  return (
    <InfoTip label={help.title} wide>
      <strong className="tip__title">{help.title}</strong>
      <dl className="tip__rows">
        <div>
          <dt>What this page is</dt>
          <dd>{help.what}</dd>
        </div>
        <div>
          <dt>Who it is for</dt>
          <dd>{help.who}</dd>
        </div>
        <div>
          <dt>What you do here</dt>
          <dd>{help.action}</dd>
        </div>
      </dl>
    </InfoTip>
  );
}
