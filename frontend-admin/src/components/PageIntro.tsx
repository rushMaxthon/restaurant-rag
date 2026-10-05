import type { ReactNode } from 'react';

import type { PageHelpId } from '../services/pageHelp';
import { PageHelpTip } from './PageHelpTip';

interface PageIntroProps {
  eyebrow: string;
  title: string;
  description: string;
  /** Which entry in `pageHelp` explains this page; puts an "i" beside the title. */
  help?: PageHelpId;
  actions?: ReactNode;
}

export function PageIntro({ eyebrow, title, description, help, actions }: PageIntroProps) {
  return (
    <header className="page-intro">
      <div className="page-intro__copy">
        <span className="eyebrow">{eyebrow}</span>
        {help ? (
          <div className="tip-row">
            <h1>{title}</h1>
            <PageHelpTip page={help} />
          </div>
        ) : (
          <h1>{title}</h1>
        )}
        <p>{description}</p>
      </div>
      {actions ? <div className="page-intro__actions">{actions}</div> : null}
    </header>
  );
}
