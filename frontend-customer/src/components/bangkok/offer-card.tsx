import { Link } from "@tanstack/react-router";
import { ArrowRight, Sparkles } from "lucide-react";
import type { PersonalizedOffer } from "@/lib/api";

/** Where a personalised offer's CTA should land, based on what it targets. */
function offerLink(offer: PersonalizedOffer): { to: "/menu/$itemId"; params: { itemId: string } } | { to: "/menu" } {
  if (offer.target_type === "ITEM" && offer.menu_item_id) {
    return { to: "/menu/$itemId", params: { itemId: offer.menu_item_id } };
  }
  return { to: "/menu" };
}

export function OfferCard({ offer }: { offer: PersonalizedOffer }) {
  const link = offerLink(offer);
  return (
    <Link {...link} className="offer-card group block shrink-0 snap-start overflow-hidden rounded-lg border border-border bg-surface p-5">
      <span className="offer-badge inline-flex items-center gap-1">
        <Sparkles className="size-3.5" />
        {offer.badge}
      </span>
      <h3 className="mt-3 font-display text-lg font-bold leading-tight">{offer.title}</h3>
      <p className="mt-1 line-clamp-2 text-sm text-muted">{offer.subtitle}</p>
      <span className="mt-4 inline-flex items-center gap-1 text-sm font-bold text-primary">
        {offer.cta_label}
        <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" />
      </span>
    </Link>
  );
}
