// The Edit parts, handed to the page as one object (`tools`). main.jsx passes this; view.jsx (the published page) passes nothing,
// so nothing under edit/ and neither stores/changes.js nor api.js is in a published file.
import { Gutter } from "./Gutter.jsx";
import { Add } from "./Add.jsx";
import { Title } from "./Title.jsx";
import { Toggle } from "./Toggle.jsx";
import { Toast } from "./Toast.jsx";
import { Cell } from "./cells/Cell.jsx";
import { Board, LayoutSwitch } from "./Board.jsx";
import { Publish } from "./Publish.jsx";
import { ProfileMenu } from "./ProfileMenu.jsx";
import { Personal } from "./Personal.jsx";
import { GLANCE } from "./GlanceEdit.jsx";
import { ClientFolder } from "./ClientFolder.jsx";
import { Movement } from "./Movement.jsx";
import { RichField } from "./RichField.jsx";
import { richOn } from "./richSave.js";
import { Safety } from "./Safety.jsx";
import { RowMenu } from "./RowMenu.jsx";
import { HelpLayer } from "../help/Help.jsx";
import { installKeys, openHelp, closeHelp, helpOpen } from "../help/helpStore.js";

// Help (#82) is among them: a published file has no Help panel and no "?" key.
export const EDIT = { glance: GLANCE, Personal, RichField, richOn, Gutter, Add, Title, Toggle, Toast, Cell, Publish, ProfileMenu, ClientFolder, Safety, MilestoneMore: Movement, Board, LayoutSwitch, RowMenu, HelpLayer, help: { open: openHelp, close: closeHelp, isOpen: () => helpOpen.value, installKeys } };
