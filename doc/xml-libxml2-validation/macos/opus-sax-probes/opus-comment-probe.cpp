#include <libxml/parser.h>
#include <cstdio>
#include <cstring>
void start(void*,const xmlChar*,const xmlChar**) {}
void end(void*,const xmlChar*) {}
int main(){for(bool fix:{false,true}){xmlSAXHandler s{};xmlSAXVersion(&s,1);s.startElement=start;s.endElement=end;if(fix){s.comment=nullptr;s.processingInstruction=nullptr;}auto p=xmlCreatePushParserCtxt(&s,nullptr,nullptr,0,"probe");p->userData=p;xmlParseChunk(p,"<root>",6,0);const char*x="<!--comment--><?target value?>";for(int i=0;i<10000;++i)xmlParseChunk(p,x,std::strlen(x),0);xmlParseChunk(p,"</root>",7,1);int n=0;if(p->myDoc)for(auto c=p->myDoc->children;c;c=c->next)++n;std::printf("callbacks_disabled=%d retained_document_nodes=%d\n",fix,n);if(p->myDoc)xmlFreeDoc(p->myDoc);xmlFreeParserCtxt(p);}}
