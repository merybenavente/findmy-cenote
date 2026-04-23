# FindMy Cenote — Dashboard Design Guidelines

A short, opinionated brief the programmers can work from. The current dashboard has all the right information; it just needs hierarchy, rhythm, and a brand-aligned skin.

## 1. Adopt the brand system

Palette (CSS variables):
- --deep:   #0B3D3A   (chrome, panels)
- --teal:   #0E6F6B   (headers, active surfaces)
- --jade:   #1FA38E   (primary accent, selected state)
- --turq:   #4FD1C5   (highlights, hover)
- --mint:   #9BE7D8   (subtle accents on dark)
- --stone:  #F3ECDC   (light surfaces)
- --cream:  #FAF6EC   (primary text on dark)
- --sun:    #F4B544   (warning / spotlight accent)
- --ink:    #0A1E1D   (app bg)

Typography:
- Space Grotesk — all UI (labels, values, headers). Weights 400/500/600.
- JetBrains Mono — numeric values only.

## 2. Information hierarchy

Three levels:
- Section header: JetBrains Mono, 10px, 0.14em tracking, uppercase, 0.5 opacity
- Control label: Space Grotesk 13px, 0.75 opacity
- Active/selected: Space Grotesk 13px 500, cream or jade

Section dividers: 1px at rgba(250,246,236,0.08), 16px padding.

## 3. Controls

Segmented buttons: 6px radius, 28px tall, jade bg when active.
Checkboxes: Custom 14px square, 3px radius, jade fill when checked.
Dropdowns: Styled chips, not native select.

## 4. Cenote list cards

One hero stat (depth) big, secondary stats in small metadata row.
No colored pills. Name 15px 600, meta mono 10px uppercase.

## 5. Map

Fit-to-bounds on load. Markers: 3px turq dots, size-encoded by depth.
Selected: 12px sun ring with pulse. Chicxulub ring: animated dash offset.

## 6. Header

Left: logo mark + wordmark. Center: search input. Right: count chip + coords.

## 7. Spacing

4px grid. 24px between sections with dividers. Sidebar padding 20px h, 16px v.

## 8. Priority order

1. Brand palette (done)
2. Styled controls
3. Redesign list cards
4. Restyle map markers
5. Animate Chicxulub ring
6. Rebuild header
