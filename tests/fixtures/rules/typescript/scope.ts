export function add(a: number, b: number): number {
  const local = 1;
  module.exports.sneaky = local;
  return a + b + local;
}

export const MAX = 1;

export class Widget {
  render(): string {
    const local = 2;
    return String(local);
  }
}
