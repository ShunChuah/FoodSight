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
  return { basemap: "map", visible, groups, fitRequest: 0, expanded: false, selected: null, tour: null };
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
      return { ...state, expanded, selected: expanded ? state.selected : null, tour: expanded ? state.tour : null };
    }
    // Opening a place's details expands the map, since the details live in its side panel.
    case "select_place":
      return typeof command.id === "string" ? { ...state, expanded: true, selected: command.id, tour: null } : state;
    case "close_place":
      return { ...state, selected: null };
    // The Cinematic AI tour: it runs on the expanded map, and stopping it puts the map back as it was.
    case "start_tour":
      return command.scenes > 0 ? { ...state, selected: null, expanded: true,
        tour: { scene: 0, scenes: command.scenes, playing: command.scenes > 1, wasExpanded: state.tour ? state.tour.wasExpanded : state.expanded } } : state;
    case "pause_tour":
      return state.tour ? { ...state, tour: { ...state.tour, playing: false } } : state;
    case "resume_tour":
      return state.tour ? { ...state, tour: { ...state.tour, playing: true } } : state;
    // The last scene still plays its explanation; the tour then stops there (scene_done).
    case "tour_step": {
      if (!state.tour) return state;
      const scene = Math.min(Math.max(state.tour.scene + (command.step ?? 1), 0), state.tour.scenes - 1);
      return scene === state.tour.scene ? state : { ...state, tour: { ...state.tour, scene } };
    }
    case "scene_done":
      if (!state.tour?.playing) return state;
      return state.tour.scene === state.tour.scenes - 1 ? { ...state, tour: { ...state.tour, playing: false } }
        : { ...state, tour: { ...state.tour, scene: state.tour.scene + 1 } };
    case "stop_tour":
      return state.tour ? { ...state, tour: null, expanded: state.tour.wasExpanded } : state;
    default:
      return state;
  }
}
