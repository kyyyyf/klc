export const PLAIN = 1;
export const TYPED: number = 2;
export function fn(): number { return 1; }
export function generic<T>(x: T): T { return x; }
export class Foo extends Bar {}
export abstract class Baz {}
export interface IFoo extends IBar {}
export type Alias = string;
export enum Color { Red, Green }
export default class DefaultCls {}

function notExported() {
  const local = 1;
  class LocalCls {}
  return local;
}
