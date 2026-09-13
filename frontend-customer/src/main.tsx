import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
// First: `@font-face` must be registered before any rule that names the family,
// and before `index.css` defines `--font-ui` in terms of it.
import './styles/fonts.css';
import './index.css';
import './styles/app.css';
// Last, deliberately: the storefront layer for Home overrides the app
// baseline above it and is scoped to `.home` so it reaches nothing else.
import './styles/home.css';
// The same layer for Menu, Orders, Cart and the doorway. Last, so it settles
// disagreements between the app baseline and the legacy rules in `index.css`.
import './styles/screens.css';
// After all four: `DishRow` replaced the two dish components those layers each
// styled separately, so its rules have to win over whatever they still say
// about the grid and list containers it lives in.
import './styles/dish-row.css';
// After the component layers: motion decorates what they lay out, and its
// reduced-motion rule must be able to override any transition they declare.
import './styles/motion.css';
import { AppRoot } from './AppRoot';
import { AppConfigProvider } from './store/AppConfigProvider';

// Opts into hidden-then-revealed. Set here rather than in the HTML so that a
// JS bundle which never boots leaves every reveal target visible.
document.documentElement.classList.add('js-motion');

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppConfigProvider>
      <AppRoot />
    </AppConfigProvider>
  </StrictMode>,
);
