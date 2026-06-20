"use strict";

const core = require("..");

const jpeg = Buffer.from([0xff, 0xd8, 0xff, 0xd9]);
const header = core.makeSignalrgbJpegHeader(jpeg);

if (header.length !== 20) throw new Error(`expected 20-byte header, got ${header.length}`);
if (header.subarray(0, 4).toString("ascii") !== "SRGB") throw new Error("bad magic");
if (header[4] !== 0x05) throw new Error("bad JPEG command");
if (header.readUInt32LE(16) !== jpeg.length) throw new Error("bad payload length");

console.log(core.protocolInfo());
