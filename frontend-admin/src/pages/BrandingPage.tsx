import { PageIntro } from "../components/PageIntro";
import { BrandingPanel } from "../components/BrandingPanel";

interface BrandingPageProps {
  token: string;
  restaurantId: string | null;
  restaurantName: string | null;
  onToast: (
    title: string,
    description: string,
    tone?: "success" | "error" | "info",
  ) => void;
}

/**
 * Branding as its own screen.
 *
 * It lives in the sidebar rather than inside the restaurant workspace because
 * an owner has exactly one restaurant: making them open it and find a tab to
 * change their app's colour buried the setting behind navigation that only
 * makes sense for an administrator managing many.
 */
export function BrandingPage({
  token,
  restaurantId,
  restaurantName,
  onToast,
}: BrandingPageProps) {
  return (
    <div className="page-stack">
      <PageIntro
        description="The accent colour your customers see throughout your app. Menus, prices and order status keep their own colours."
        eyebrow="Customer app"
        title="Branding"
      />
      {restaurantId ? (
        <section className="admin-surface bp-surface">
          <BrandingPanel
            onToast={onToast}
            restaurantId={restaurantId}
            restaurantName={restaurantName ?? "Your restaurant"}
            token={token}
          />
        </section>
      ) : (
        <section className="admin-surface">
          <p className="hint-text">
            No restaurant is assigned to this account yet, so there is nothing to
            brand.
          </p>
        </section>
      )}
    </div>
  );
}
