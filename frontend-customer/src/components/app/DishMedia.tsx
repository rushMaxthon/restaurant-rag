import { useState } from 'react';

import { createPlaceholderImage } from '../../services/api';

/**
 * A dish's picture, in the three states it actually occurs in.
 *
 * Extracted rather than left inline because four surfaces render a dish image
 * and they must not drift: consolidating two card components previously kept
 * one's grey-box fallback and silently dropped the other's branded
 * placeholder, which is why every card showed a grey box.
 *
 * Production has no upload pipeline — an owner pastes a URL into a text field
 * and this hotlinks it. So the failure path is ordinary, not exceptional: the
 * link rots, the host blocks hotlinking, and the dish spends the rest of its
 * life in the placeholder state. It is designed for that, not patched for it.
 *
 * The box reserves its aspect ratio in CSS before the image loads, because
 * nothing controls the source dimensions and an unreserved box makes the whole
 * grid jump as photographs arrive.
 */
export function DishMedia({
  name,
  imageUrl,
  variant = 'grid',
}: {
  name: string;
  imageUrl: string | null;
  variant?: 'grid' | 'compact' | 'detail';
}) {
  const [failed, setFailed] = useState(false);
  const src = !imageUrl || failed ? createPlaceholderImage(name) : imageUrl;

  return (
    <span className={`dish-media dish-media--${variant}`}>
      <img
        alt=""
        decoding="async"
        loading="lazy"
        onError={() => setFailed(true)}
        src={src}
      />
    </span>
  );
}
