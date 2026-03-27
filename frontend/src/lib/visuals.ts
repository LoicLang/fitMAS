const HERO_BACKDROPS: Record<string, string> = {
  running: "https://images.unsplash.com/photo-1473448912268-2022ce9509d8?auto=format&fit=crop&w=1800&q=80",
  cycling: "https://images.unsplash.com/photo-1507035895480-2b3156c31fc8?auto=format&fit=crop&w=1800&q=80",
  swimming: "https://images.unsplash.com/photo-1519315901367-f34ff9154487?auto=format&fit=crop&w=1800&q=80",
  climbing: "https://images.unsplash.com/photo-1522163182402-834f871fd851?auto=format&fit=crop&w=1800&q=80",
  strength: "https://images.unsplash.com/photo-1517838277536-f5f99be501cd?auto=format&fit=crop&w=1800&q=80",
  rest: "https://images.unsplash.com/photo-1500530855697-b586d89ba3ee?auto=format&fit=crop&w=1800&q=80",
};

const CARD_BACKDROPS: Record<string, string> = {
  running: "https://images.unsplash.com/photo-1502224562085-639556652f33?auto=format&fit=crop&w=1400&q=80",
  cycling: "https://images.unsplash.com/photo-1517649763962-0c623066013b?auto=format&fit=crop&w=1400&q=80",
  swimming: "https://images.unsplash.com/photo-1600965962361-9035dbfd1c50?auto=format&fit=crop&w=1400&q=80",
  climbing: "https://images.unsplash.com/photo-1522163182402-834f871fd851?auto=format&fit=crop&w=1400&q=80",
  strength: "https://images.unsplash.com/photo-1517836357463-d25dfeac3438?auto=format&fit=crop&w=1400&q=80",
  rest: "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?auto=format&fit=crop&w=1400&q=80",
};

export function getHeroBackdrop(sport?: string | null) {
  return HERO_BACKDROPS[sport || "rest"] || HERO_BACKDROPS.rest;
}

export function getCardBackdrop(sport?: string | null) {
  return CARD_BACKDROPS[sport || "rest"] || CARD_BACKDROPS.rest;
}
