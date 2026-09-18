export const PLAIN = 1;
export function fn() { return 1; }
export class Foo {}
export default function Named() {}
module.exports.Bar = 2;

function notExported() {
  const local = 1;
  return local;
}
