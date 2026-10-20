#include <libxml/parser.h>
#include <cstdio>
#include <cstring>
void error(void*, const xmlError* e) { std::printf("level=%d code=%d message=%s", e->level,e->code,e->message); }
void start(void*,const xmlChar*,const xmlChar*,const xmlChar*,int,const xmlChar**,int,int,const xmlChar**) {}
int main(){ xmlSAXHandler s{};xmlSAXVersion(&s,2);s.startElementNs=start;s.comment=nullptr;s.processingInstruction=nullptr;auto p=xmlCreatePushParserCtxt(&s,nullptr,nullptr,0,"probe");xmlCtxtSetErrorHandler(p,error,nullptr);const char*x="<root xmlns='relative'/>";int r=xmlParseChunk(p,x,std::strlen(x),1);std::printf("return=%d\n",r);if(p->myDoc)xmlFreeDoc(p->myDoc);xmlFreeParserCtxt(p); }
