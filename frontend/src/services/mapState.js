import { overlayGroups } from "./mapOverlays.js";

// Every map change goes through a command (see MAP_COMMANDS), so buttons and chat can drive the map the same way.
export const BASEMAPS = ["map", "satellite"];
export const MAP_COMMANDS = {
  set_basemap: { basemap: BASEMAPS },
  toggle_basemap: {},
  toggle_overlay: { overlay: ["areas", "radius", "density"], visible: [true, false, undefined] },
  reset_view: {},
  expand_map: { expanded: [true, false, undefined] },
  select_place: { id: "a place id on this map" },
  close_place: {},
};

export function initialMapState(mapData) {
  const groups = overlayGroups(mapData).map((group) => group.id);
  const visible = Object.fromEntries(groups.map((id) => [id, true]));
  // A heatmap over area outlines hides them, so it starts off when areas are shown.
  if (visible.density && visible.areas) visible.density = false;
  return { basemap: "map", visible, groups, fitRequest: 0, expanded: false, selected: null };
}

export function applyMapCommand(state, command) {
  switch (command?.type) {
    case "load":
      return initialMapState(command.mapData);
    case "set_basemap":
      return BASEMAPS.includes(command.basemap) ? { ...state, basemap: command.basemap } : state;
    case "toggle_basemap":
      return { ...state, basemap: state.basemap === "satellite" ? "map" : "satellite" };
    case "toggle_overlay": {
      if (!state.groups.includes(command.overlay)) return state;
      const visible = typeof command.visible === "boolean" ? command.visible : !state.visible[command.overlay];
      if (visible === state.visible[command.overlay]) return state;
      return { ...state, visible: { ...state.visible, [command.overlay]: visible } };
    }
    case "reset_view":
      return { ...state, fitRequest: state.fitRequest + 1 };
    case "expand_map": {
      const expanded = typeof command.expanded === "boolean" ? command.expanded : !state.expanded;
      return { ...state, expanded, selected: expanded ? state.selected : null };
    }
    // Opening a place's details expands the map, since the details live in its side panel.
    case "select_place":
      return typeof command.id === "string" ? { ...state, expanded: true, selected: command.id } : state;
    case "close_place":
      return { ...state, selected: null };
    default:
      return state;
  }
}
