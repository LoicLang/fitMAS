const SESSION_IMAGES: Record<string, string> = {
  running: "https://images.unsplash.com/photo-1473448912268-2022ce9509d8?auto=format&fit=crop&w=1800&q=80",
  cycling: "https://images.unsplash.com/photo-1507035895480-2b3156c31fc8?auto=format&fit=crop&w=1800&q=80",
  swimming: "https://images.unsplash.com/photo-1519315901367-f34ff9154487?auto=format&fit=crop&w=1800&q=80",
  climbing: "https://images.unsplash.com/photo-1522163182402-834f871fd851?auto=format&fit=crop&w=1800&q=80",
  strength: "https://images.unsplash.com/photo-1517836357463-d25dfeac3438?auto=format&fit=crop&w=1800&q=80",
  rest: "https://images.unsplash.com/photo-1441974231531-c6227db76b6e?auto=format&fit=crop&w=1800&q=80",
};

export function sessionBackdrop(sportType?: string | null) {
  if (!sportType) return SESSION_IMAGES.rest;
  return SESSION_IMAGES[sportType] || SESSION_IMAGES.rest;
}
