import { Link } from "@tanstack/react-router";
import { Plus, Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DishImage } from "./dish-image";
import { VegMark } from "./veg-mark";
import { formatINR, type MenuItem } from "@/lib/bangkok-data";
import { useBangkokStore } from "@/lib/bangkok-store";
export function DishCard({ item }: { item: MenuItem }) {
 const { addItem } = useBangkokStore();
 // The cart lives in localStorage, so a guest can fill one without an account.
 // Sign-in is asked for once, at checkout, where it actually buys something.
 function handleAdd() {
  addItem(item);
 }
 return <article className="dish-card group overflow-hidden rounded-lg border border-border bg-surface">
 <Link to="/menu/$itemId" params={{ itemId: item.id }} className="block overflow-hidden"><DishImage src={item.image_url} name={item.name} className="transition-transform duration-300 group-hover:scale-[1.03]" /></Link>
 <div className="space-y-3 p-4"><div className="flex items-start justify-between gap-3"><div className="min-w-0"><div className="mb-1 flex items-center gap-2"><VegMark veg={item.is_veg} />{item.is_bestseller && <span className="text-xs font-bold text-primary">BESTSELLER</span>}{item.is_new && <span className="text-xs font-bold text-success">NEW</span>}</div><Link to="/menu/$itemId" params={{ itemId: item.id }} className="font-display text-lg font-bold leading-tight hover:text-primary">{item.name}</Link></div>{item.rating && <span className="flex shrink-0 items-center gap-1 text-sm font-semibold"><Star className="size-4 fill-primary text-primary" />{item.rating}</span>}</div>
 <p className="line-clamp-2 min-h-10 text-sm text-muted">{item.description}</p><div className="flex items-center justify-between gap-3"><span className="font-bold">{item.has_sizes ? `From ${formatINR(item.price)}` : formatINR(item.price)}</span><Button aria-label={`Add ${item.name}`} size="icon" disabled={!item.is_available} onClick={handleAdd}><Plus /></Button></div></div></article>;
}
