import { useState } from "react";
import { cn } from "@/lib/utils";
const tones = ["placeholder-a", "placeholder-b", "placeholder-c", "placeholder-d"];
export function DishImage({ src, name, className, priority = false }: { src: string | null; name: string; className?: string; priority?: boolean }) {
 const [failed, setFailed] = useState(false); const initials = name.split(" ").map((p) => p[0]).slice(0, 2).join(""); const tone = tones[name.length % tones.length];
 if (!src || failed) return <div role="img" aria-label={`${name} placeholder`} className={cn("dish-placeholder flex aspect-[4/3] items-center justify-center text-3xl font-extrabold", tone, className)}><span>{initials}</span></div>;
 return <img src={src} alt={name} width={900} height={700} loading={priority ? "eager" : "lazy"} onError={() => setFailed(true)} className={cn("aspect-[4/3] w-full object-cover", className)} />;
}
