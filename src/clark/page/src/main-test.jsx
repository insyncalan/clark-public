import { boot } from "./boot.jsx";
import { EDIT } from "./edit/index.js";
import { install } from "./testhook.js";

install(EDIT);
boot(EDIT);
